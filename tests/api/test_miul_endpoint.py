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

import asyncio
import json
import uuid
import pytest
from fastapi.testclient import TestClient
from io import BytesIO
from pathlib import Path

from mira.core.session_store import reset_session_store

_TMP_ROOT = Path(__file__).resolve().parents[2] / ".tmp_tests"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _make_temp_dir() -> str:
    temp_dir = _TMP_ROOT / f"miul-api-{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return str(temp_dir)


@pytest.fixture
def client():
    """Create test client for API."""
    from mira.api.app import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_shared_session_store():
    reset_session_store()
    yield
    reset_session_store()


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
        # Verify router responds to POST fast-extract (even without file)
        response = client.post("/miul/fast-extract")
        # Should get validation error (422) for missing files, not 404 (router not found)
        assert response.status_code == 422

    def test_v4_status_endpoint_supports_suspending_session_store(self, client, monkeypatch):
        """V4 status route must work when the shared store actually awaits."""

        from mira.api.routers import miul as miul_router

        def _sync_await(value):
            async def _inner():
                await asyncio.sleep(0)
                return value

            return asyncio.run(_inner())

        class FakeV4Session:
            _status_by_id = {
                "async-status-1": {
                    "extraction_id": "async-status-1",
                    "status": "extracting",
                    "message": "Working",
                    "progress": 35,
                }
            }

            def __init__(self, extraction_id):
                self.extraction_id = extraction_id

            def get_owner_username(self):
                return _sync_await(None)

            def get_status(self):
                return _sync_await(self._status_by_id[self.extraction_id])

        monkeypatch.setattr(miul_router, "_V4Session", FakeV4Session)

        response = client.get("/miul/v4/extract/async-status-1/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "extracting"
        assert data["progress"] == 35

    def test_v4_extract_returns_queued_when_sqs_enqueue_succeeds(self, client, monkeypatch):
        """SQS-backed submissions should stay queued until the worker starts."""

        from mira.api.routers import miul as miul_router
        from mira.miul import queue as miul_queue

        class FakeV4Session:
            _status_by_id = {}
            _owner_by_id = {}

            def __init__(self, extraction_id):
                self.extraction_id = extraction_id

            def set_owner_username(self, owner_username):
                self._owner_by_id[self.extraction_id] = owner_username

            def set_status(self, status, message="", progress=0, summary=None, error=None):
                payload = {
                    "extraction_id": self.extraction_id,
                    "status": status,
                    "message": message,
                    "progress": progress,
                }
                if summary is not None:
                    payload["summary"] = summary
                if error is not None:
                    payload["error"] = error
                self._status_by_id[self.extraction_id] = payload

            def get_owner_username(self):
                return self._owner_by_id.get(self.extraction_id)

            def get_status(self):
                return self._status_by_id[self.extraction_id]

            @property
            def exists(self):
                return self.extraction_id in self._status_by_id

        monkeypatch.setattr(miul_router, "_V4Session", FakeV4Session)
        monkeypatch.setattr(miul_queue, "enqueue_extraction", lambda **kwargs: True)
        monkeypatch.setattr(miul_router.tempfile, "mkdtemp", lambda *args, **kwargs: _make_temp_dir())

        files = {
            "drawings": ("drawing.pdf", BytesIO(b"%PDF-1.4 fake"), "application/pdf"),
            "drawing_tree_json": ("tree.json", BytesIO(json.dumps({"tree": []}).encode("utf-8")), "application/json"),
        }
        response = client.post("/miul/v4/extract", files=files)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"


class TestMIULFastExtract:
    """Tests for MIUL fast-extract endpoint (BOM extraction from PDFs)."""

    def test_fast_extract_requires_files(self, client):
        """Fast extract requires PDF files."""
        response = client.post("/miul/fast-extract")
        assert response.status_code == 422

    def test_fast_extract_rejects_non_pdf(self, client):
        """Fast extract rejects non-PDF files."""
        # Create a fake text file
        fake_file = BytesIO(b"This is not a PDF")
        response = client.post(
            "/miul/fast-extract",
            files={"drawings": ("test.txt", fake_file, "text/plain")},
        )
        # Should return 400 (bad request) for invalid file type
        assert response.status_code in [400, 422]


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
    """Tests for MSFC drawing extraction endpoint."""

    def test_msfc_requires_files(self, client):
        """MSFC extract requires at least one input."""
        response = client.post("/miul/msfc-extract")
        # Should require either DT or drawings
        assert response.status_code in [400, 422]


class TestMIULDMLLVExtract:
    """Tests for DMLLV extraction endpoint."""

    def test_dmllv_requires_files(self, client):
        """DMLLV extract requires PDF files."""
        response = client.post("/miul/dmllv-extract")
        assert response.status_code == 422


__safety_critical__ = True
