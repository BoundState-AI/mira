"""
Tests for MIUL v4 extraction queue and worker.

Covers:
  - enqueue_extraction returns False when no SQS URL configured
  - enqueue_extraction returns True when SQS is mocked
  - handle_extraction_message processes valid jobs
  - handle_extraction_message rejects malformed messages
  - handle_extraction_message is idempotent (skips completed jobs)
  - handle_extraction_message records failures in session status
  - worker updates shared state correctly

BoundState AI 2026
Classification: BoundState Proprietary
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mira.core.session_store import reset_session_store
from mira.miul.queue import enqueue_extraction, get_queue_url
from mira.miul.worker import handle_extraction_message

_TMP_ROOT = Path(__file__).resolve().parents[2] / ".tmp_tests"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _make_temp_dir() -> Path:
    temp_dir = _TMP_ROOT / f"miul-worker-{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


@pytest.fixture(autouse=True)
def _clean_env():
    reset_session_store()
    old_url = os.environ.pop("MIUL_EXTRACTION_QUEUE_URL", None)
    yield
    reset_session_store()
    if old_url is not None:
        os.environ["MIUL_EXTRACTION_QUEUE_URL"] = old_url
    else:
        os.environ.pop("MIUL_EXTRACTION_QUEUE_URL", None)


# ---------------------------------------------------------------------------
# Queue helper tests
# ---------------------------------------------------------------------------


class TestEnqueue:
    def test_no_queue_url_returns_false(self):
        """Without MIUL_EXTRACTION_QUEUE_URL, enqueue returns False."""
        assert get_queue_url() is None
        result = enqueue_extraction(
            extraction_id="test-1",
            pdf_filenames=["a.pdf"],
            dt_json={},
            temp_dir="/tmp/test",
        )
        assert result is False

    def test_with_queue_url_sends_message(self):
        """Standard queues should not receive FIFO-only message parameters."""
        os.environ["MIUL_EXTRACTION_QUEUE_URL"] = "https://sqs.us-gov-west-1.amazonaws.com/123/miul-queue"

        mock_client = MagicMock()
        mock_client.send_message.return_value = {"MessageId": "msg-abc"}
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            result = enqueue_extraction(
                extraction_id="test-2",
                pdf_filenames=["drawing1.pdf", "drawing2.pdf"],
                dt_json={"tree": []},
                temp_dir="/tmp/test",
                project="Artemis",
            )

        assert result is True
        mock_client.send_message.assert_called_once()
        call_kwargs = mock_client.send_message.call_args[1]
        assert "MessageGroupId" not in call_kwargs
        assert "MessageDeduplicationId" not in call_kwargs

        body = json.loads(call_kwargs["MessageBody"])
        assert body["extraction_id"] == "test-2"
        assert body["pdf_filenames"] == ["drawing1.pdf", "drawing2.pdf"]
        assert body["project"] == "Artemis"

    def test_fifo_queue_sends_fifo_fields(self):
        """FIFO queues should include group/deduplication fields."""
        os.environ["MIUL_EXTRACTION_QUEUE_URL"] = "https://sqs.us-gov-west-1.amazonaws.com/123/miul-queue.fifo"

        mock_client = MagicMock()
        mock_client.send_message.return_value = {"MessageId": "msg-fifo"}
        mock_boto3 = MagicMock()
        mock_boto3.client.return_value = mock_client

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            result = enqueue_extraction(
                extraction_id="fifo-1",
                pdf_filenames=["drawing1.pdf"],
                dt_json={},
                temp_dir="/tmp/test",
            )

        assert result is True
        call_kwargs = mock_client.send_message.call_args[1]
        assert call_kwargs["MessageGroupId"] == "miul-extraction"
        assert call_kwargs["MessageDeduplicationId"] == "fifo-1"

    def test_enqueue_failure_returns_false(self):
        """If boto3 raises, enqueue returns False (doesn't crash)."""
        os.environ["MIUL_EXTRACTION_QUEUE_URL"] = "https://sqs.example.com/queue"

        mock_boto3 = MagicMock()
        mock_boto3.client.side_effect = Exception("no credentials")

        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            result = enqueue_extraction(
                extraction_id="test-3",
                pdf_filenames=["a.pdf"],
                dt_json={},
                temp_dir="/tmp/test",
            )

        assert result is False


# ---------------------------------------------------------------------------
# Worker handler tests
# ---------------------------------------------------------------------------


class TestWorkerHandler:
    def test_rejects_missing_extraction_id(self):
        """Message without extraction_id returns False."""
        result = handle_extraction_message({"pdf_filenames": ["a.pdf"]})
        assert result is False

    def test_rejects_missing_temp_dir(self):
        """Message without temp_dir returns False."""
        result = handle_extraction_message({
            "extraction_id": "test-4",
            "pdf_filenames": ["a.pdf"],
        })
        assert result is False

    def test_records_failure_when_files_missing(self):
        """Worker records failed status when PDFs are not accessible."""
        from mira.miul.production.session import V4Session

        session = V4Session("test-missing-files")
        session.set_owner_username("test-user")
        session.set_status("queued", progress=0)

        result = handle_extraction_message({
            "extraction_id": "test-missing-files",
            "pdf_filenames": ["nonexistent.pdf"],
            "dt_json": {},
            "temp_dir": "/nonexistent/path",
        })

        assert result is True  # Processed (not retryable)
        status = V4Session("test-missing-files").get_status()
        assert status["status"] == "failed"
        assert "file_access_error" in (status.get("error") or "")

    def test_idempotent_skip_completed(self):
        """Completed jobs are skipped before temp-file validation."""
        from mira.miul.production.session import V4Session

        session = V4Session("test-idempotent")
        session.set_owner_username("user")
        session.set_status("complete", progress=100, summary={"total_materials": 5})

        result = handle_extraction_message({
            "extraction_id": "test-idempotent",
            "pdf_filenames": ["a.pdf"],
            "dt_json": {},
            "temp_dir": "/tmp/cleaned-up",
        })

        assert result is True
        status = V4Session("test-idempotent").get_status()
        assert status["status"] == "complete"

    def test_idempotent_skip_failed(self):
        """Failed jobs are skipped before temp-file validation."""
        from mira.miul.production.session import V4Session

        session = V4Session("test-idempotent-fail")
        session.set_status("failed", error="previous error")

        result = handle_extraction_message({
            "extraction_id": "test-idempotent-fail",
            "pdf_filenames": ["a.pdf"],
            "dt_json": {},
            "temp_dir": "/tmp/test",
        })

        assert result is True
        status = V4Session("test-idempotent-fail").get_status()
        assert status["status"] == "failed"

    def test_successful_extraction_updates_status(self):
        """Worker processes a real extraction and saves complete status."""
        from mira.miul.production.session import V4Session

        session = V4Session("test-success")
        session.set_owner_username("test-user")
        session.set_status("queued")

        # Create a temp dir with a fake PDF
        temp_dir = _make_temp_dir()
        pdf_path = temp_dir / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake content")

        # Mock the extractor to avoid real Sonnet calls
        mock_result = MagicMock()
        mock_result.extraction_id = "test-success"
        mock_result.summary = {"total_materials": 3, "needs_review": 1}
        mock_result.materials = []
        mock_result.drawing_packages = []
        mock_result.to_dict.return_value = {
            "extraction_id": "test-success",
            "timestamp": "2026-04-01T00:00:00Z",
            "materials": [],
            "drawing_packages": [],
            "summary": {"total_materials": 3, "needs_review": 1},
        }

        mock_extractor = MagicMock()
        mock_extractor.extract_from_files.return_value = mock_result

        with patch("mira.miul.worker._get_extractor", return_value=mock_extractor):
            with patch("mira.miul.production.session._identify_review_items") as mock_review:
                mock_review.return_value = {
                    "summary": {"total_materials": 3, "needs_review": 1, "auto_approved": 2},
                    "review_items": [],
                }

                result = handle_extraction_message({
                    "extraction_id": "test-success",
                    "pdf_filenames": ["test.pdf"],
                    "dt_json": {},
                    "temp_dir": str(temp_dir),
                })

        assert result is True
        status = V4Session("test-success").get_status()
        assert status["status"] == "complete"
        assert status["progress"] == 100
        assert status["summary"]["total_materials"] == 3

        # Temp dir should be cleaned up
        assert not temp_dir.exists()

    def test_extraction_failure_records_error(self):
        """Worker records error details when extraction raises."""
        from mira.miul.production.session import V4Session

        session = V4Session("test-fail")
        session.set_owner_username("test-user")
        session.set_status("queued")

        temp_dir = _make_temp_dir()
        pdf_path = temp_dir / "bad.pdf"
        pdf_path.write_bytes(b"not a pdf")

        mock_extractor = MagicMock()
        mock_extractor.extract_from_files.side_effect = RuntimeError("OCR engine crashed")

        with patch("mira.miul.worker._get_extractor", return_value=mock_extractor):
            result = handle_extraction_message({
                "extraction_id": "test-fail",
                "pdf_filenames": ["bad.pdf"],
                "dt_json": {},
                "temp_dir": str(temp_dir),
            })

        assert result is True
        status = V4Session("test-fail").get_status()
        assert status["status"] == "failed"
        assert "OCR engine crashed" in status["error"]

        # Temp dir should be cleaned up even on failure
        assert not temp_dir.exists()
