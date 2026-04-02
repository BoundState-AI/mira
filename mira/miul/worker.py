"""
Module: MIUL Extraction Worker
Purpose: Consumes SQS extraction jobs and runs the Sonnet Vision pipeline.

Can be run as:
    python -m mira.miul.worker          (long-poll loop)
    python -m mira.miul.worker --once   (process one message and exit)

Or invoked programmatically via ``handle_extraction_message()`` for
testing and ECS task integration.

Environment variables:
    MIUL_EXTRACTION_QUEUE_URL - SQS queue URL (required for polling)
    MIUL_WORKER_VISIBILITY_TIMEOUT - seconds before SQS redelivers (default 900)

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
import shutil
import time
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

_VISIBILITY_TIMEOUT = int(os.environ.get("MIUL_WORKER_VISIBILITY_TIMEOUT", "900"))


def _get_extractor():
    """Lazy-load the MIULVisionExtractor (avoids import at module load)."""
    from mira.miul.production.extractor import MIULVisionExtractor

    return MIULVisionExtractor()


def handle_extraction_message(body: dict[str, Any]) -> bool:
    """Process a single extraction job message.

    Returns True when the message was handled and should be deleted from SQS.
    Returns False only for malformed messages.
    """
    extraction_id = body.get("extraction_id")
    if not extraction_id:
        LOGGER.error("[MIUL-WORKER] Message missing extraction_id: %s", body)
        return False

    pdf_filenames: list[str] = body.get("pdf_filenames", [])
    dt_json: dict[str, Any] = body.get("dt_json", {})
    temp_dir_str: str = body.get("temp_dir", "")

    if not temp_dir_str or not pdf_filenames:
        LOGGER.error("[MIUL-WORKER] Message missing temp_dir or pdf_filenames")
        return False

    from mira.miul.production.session import V4Session

    session = V4Session(extraction_id)
    current_status = session.get_status()
    if current_status.get("status") in ("complete", "failed"):
        LOGGER.info(
            "[MIUL-WORKER] Extraction %s already %s; skipping (idempotent)",
            extraction_id,
            current_status["status"],
        )
        return True

    temp_dir = Path(temp_dir_str)
    pdf_paths = [temp_dir / fname for fname in pdf_filenames]

    # Validate files after the terminal-state guard so redeliveries do not
    # downgrade already-finished jobs after temp-dir cleanup.
    missing = [p for p in pdf_paths if not p.exists()]
    if missing:
        LOGGER.error(
            "[MIUL-WORKER] %d PDF files not found in %s: %s",
            len(missing),
            temp_dir,
            [p.name for p in missing],
        )
        session.set_status(
            "failed",
            f"Worker could not access {len(missing)} uploaded PDF(s). "
            "Files may have been cleaned up before the worker started.",
            progress=0,
            error="file_access_error",
        )
        return True

    LOGGER.info(
        "[MIUL-WORKER] Starting extraction %s: %d PDFs in %s",
        extraction_id,
        len(pdf_paths),
        temp_dir,
    )

    try:
        session.set_status("extracting", "Running OCR scan...", progress=5)

        extractor = _get_extractor()
        result = extractor.extract_from_files(pdf_paths, dt_json)
        result.extraction_id = extraction_id

        session.set_status("saving", "Saving results...", progress=90)
        session.save_extraction(result)

        summary = result.summary
        session.set_status(
            "complete",
            f"{summary.get('total_materials', 0)} materials extracted",
            progress=100,
            summary=summary,
        )

        LOGGER.info(
            "[MIUL-WORKER] Extraction %s complete: %d materials, %d need review",
            extraction_id,
            summary.get("total_materials", 0),
            summary.get("needs_review", 0),
        )
    except Exception as exc:
        LOGGER.error(
            "[MIUL-WORKER] Extraction %s failed: %s",
            extraction_id,
            exc,
            exc_info=True,
        )
        session.set_status("failed", str(exc), progress=0, error=str(exc))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return True


def poll_loop(*, once: bool = False) -> None:
    """Long-poll the SQS queue and process messages."""
    from .queue import get_queue_url

    queue_url = get_queue_url()
    if not queue_url:
        raise RuntimeError(
            "MIUL_EXTRACTION_QUEUE_URL is not set. "
            "Cannot start the worker without a queue."
        )

    import boto3

    region = os.environ.get(
        "MIUL_QUEUE_REGION",
        os.environ.get("AWS_REGION", "us-gov-west-1"),
    )
    client = boto3.client("sqs", region_name=region)

    LOGGER.info("[MIUL-WORKER] Starting poll loop on %s", queue_url)

    while True:
        try:
            resp = client.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=20,
                VisibilityTimeout=_VISIBILITY_TIMEOUT,
            )

            messages = resp.get("Messages", [])
            if not messages:
                if once:
                    LOGGER.info("[MIUL-WORKER] No messages; exiting (--once)")
                    return
                continue

            msg = messages[0]
            receipt = msg["ReceiptHandle"]

            try:
                body = json.loads(msg["Body"])
            except (json.JSONDecodeError, KeyError):
                LOGGER.error("[MIUL-WORKER] Malformed message: %s", msg.get("Body"))
                client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
                if once:
                    return
                continue

            handle_extraction_message(body)

            # Failures are recorded in shared state, so we delete either way.
            client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
            LOGGER.info(
                "[MIUL-WORKER] Deleted SQS message for %s",
                body.get("extraction_id"),
            )

            if once:
                return

        except KeyboardInterrupt:
            LOGGER.info("[MIUL-WORKER] Interrupted; shutting down")
            return
        except Exception:
            LOGGER.exception("[MIUL-WORKER] Poll loop error; sleeping 5s")
            if once:
                return
            time.sleep(5)


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    poll_loop(once="--once" in sys.argv)
