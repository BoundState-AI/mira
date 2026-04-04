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
import os
from fastapi.testclient import TestClient
from io import BytesIO
from unittest.mock import patch


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

    def test_extract_dt_clamps_interactive_iterations_to_one(self, client):
        """Interactive DT extraction should clamp validation retries to keep latency bounded."""
        captured: dict[str, int] = {}

        def _fake_extract(pdf_path, client_obj, max_iterations=3):
            captured["max_iterations"] = max_iterations
            return {"top_level": "ROOT", "tree": [{"drawing_number": "ROOT", "title": "Root", "parent": None, "type": "ASSEMBLY"}]}

        fake_pdf = BytesIO(b"%PDF-1.4\n% fake drawing tree\n")
        with patch("mira.miul.v3.extract.extract_drawing_tree", side_effect=_fake_extract), \
             patch("mira.miul.v3.extract.VisionClient"):
            response = client.post(
                "/miul/extract-dt",
                data={"max_iterations": "3"},
                files={"dt_file": ("tree.pdf", fake_pdf, "application/pdf")},
            )

        assert response.status_code == 200
        assert captured["max_iterations"] == 1

    def test_fast_extract_alias_rejects_non_pdf(self, client):
        fake_file = BytesIO(b"not a pdf")
        response = client.post(
            "/miul/fast-extract",
            files=[("drawings", ("test.txt", fake_file, "text/plain"))],
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
        response = client.post("/miul/msfc-extract")
        assert response.status_code == 400


class TestMIULDMLLVExtract:
    """Tests for MIUL DT extraction parameter validation."""

    def test_dmllv_requires_files(self, client):
        response = client.post("/miul/dmllv-extract")
        assert response.status_code == 422


class TestMIULV4Extract:
    """Tests for queued MIUL v4 extraction."""

    def test_v4_extract_queues_job_when_worker_mode_enabled(self, client, monkeypatch):
        written_artifacts: dict[tuple[str, str], object] = {}
        queued_payload: dict[str, object] = {}

        monkeypatch.setenv("MIUL_EXTRACTION_QUEUE_URL", "https://example.com/queue")
        monkeypatch.setenv("MIUL_EXTRACTION_BUCKET", "test-miul-bucket")

        from mira.api.routers import miul as miul_router

        def _fake_write(self, name, data):
            written_artifacts[(self.extraction_id, name)] = data

        def _fake_upload_bytes(self, name, payload, *, content_type="application/pdf"):
            return f"inputs/{self.extraction_id}/{name}"

        def _fake_upload_json(self, name, data):
            return f"inputs/{self.extraction_id}/{name}"

        def _fake_enqueue(payload):
            queued_payload.update(payload)
            return {"message_id": "msg-1", "queued_at": "2026-04-04T00:00:00Z"}

        monkeypatch.setattr(miul_router.MIULArtifactStore, "write_session_json", _fake_write)
        monkeypatch.setattr(miul_router.MIULArtifactStore, "upload_input_bytes", _fake_upload_bytes)
        monkeypatch.setattr(miul_router.MIULArtifactStore, "upload_input_json", _fake_upload_json)
        monkeypatch.setattr(miul_router, "enqueue_extraction_job", _fake_enqueue)

        drawing = BytesIO(b"%PDF-1.4 queued drawing\n")
        drawing_tree = BytesIO(b'{"top_level":"MER07540-001","tree":[]}')

        response = client.post(
            "/miul/v4/extract",
            data={"project": "MER07540"},
            files=[
                ("drawings", ("A-1.pdf", drawing, "application/pdf")),
                ("drawing_tree_json", ("dt.json", drawing_tree, "application/json")),
            ],
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "queued"
        assert queued_payload["project"] == "MER07540"
        assert len(queued_payload["pdf_inputs"]) == 1
        assert queued_payload["dt_json_key"] == f"inputs/{payload['extraction_id']}/drawing_tree.json"
        assert written_artifacts[(payload["extraction_id"], "status.json")]["status"] == "queued"
        assert written_artifacts[(payload["extraction_id"], "metadata.json")]["owner_username"] is None


__safety_critical__ = True
