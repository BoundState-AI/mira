"""
Module: MIUL Extraction Queue
Purpose: SQS-backed job queue for MIUL v4 extraction work.

The API process enqueues extraction jobs; a separate worker process
consumes them.  In development (no SQS URL configured), jobs run
in-process via ``asyncio.to_thread`` as a fallback.

Environment variables:
    MIUL_EXTRACTION_QUEUE_URL — SQS queue URL.  If empty, falls back
                                to in-process execution.

BoundState AI 2026
Classification: BoundState Proprietary

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
Co-Authored-By: Dr. Joseph Wilde, BoundState AI

Compliance: SWE-013, SWE-032
Safety Critical: False
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

LOGGER = logging.getLogger(__name__)


def get_queue_url() -> str | None:
    """Return the SQS queue URL, or None if not configured."""
    return os.environ.get("MIUL_EXTRACTION_QUEUE_URL", "").strip() or None


def _is_fifo_queue(queue_url: str) -> bool:
    """Return True when the configured queue URL points at a FIFO queue."""
    return queue_url.rstrip("/").lower().endswith(".fifo")


def enqueue_extraction(
    extraction_id: str,
    pdf_filenames: list[str],
    dt_json: dict[str, Any],
    temp_dir: str,
    project: str = "",
) -> bool:
    """Enqueue an extraction job to SQS.

    Parameters
    ----------
    extraction_id : str
        The session/job ID (already persisted in the shared store).
    pdf_filenames : list[str]
        Filenames within *temp_dir* to process.
    dt_json : dict
        Drawing-tree JSON (may be empty dict for no-DT mode).
    temp_dir : str
        Path to the temp directory holding uploaded PDFs.
    project : str
        Optional project name.

    Returns
    -------
    bool
        True if the message was sent to SQS, False if SQS is not
        configured (caller should fall back to in-process execution).
    """
    queue_url = get_queue_url()
    if not queue_url:
        LOGGER.debug("[MIUL-QUEUE] No SQS URL configured; skipping enqueue")
        return False

    message_body = json.dumps({
        "extraction_id": extraction_id,
        "pdf_filenames": pdf_filenames,
        "dt_json": dt_json,
        "temp_dir": temp_dir,
        "project": project,
    })

    try:
        import boto3

        region = os.environ.get(
            "MIUL_QUEUE_REGION",
            os.environ.get("AWS_REGION", "us-gov-west-1"),
        )
        client = boto3.client("sqs", region_name=region)
        send_kwargs = {
            "QueueUrl": queue_url,
            "MessageBody": message_body,
        }
        if _is_fifo_queue(queue_url):
            send_kwargs["MessageGroupId"] = "miul-extraction"
            send_kwargs["MessageDeduplicationId"] = extraction_id

        resp = client.send_message(
            **send_kwargs,
        )
        message_id = resp.get("MessageId", "unknown")
        LOGGER.info(
            "[MIUL-QUEUE] Enqueued extraction %s → SQS message %s",
            extraction_id, message_id,
        )
        return True

    except Exception:
        LOGGER.exception(
            "[MIUL-QUEUE] Failed to enqueue extraction %s", extraction_id,
        )
        return False
