#!/usr/bin/env python3
"""
Dedicated MIUL extraction worker.

Consumes extraction jobs from SQS, downloads staged inputs from shared MIUL
storage, runs the existing v4 extraction path, and updates shared session
artifacts for the API to poll.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from mira.miul.production.session import V4Session
from mira.miul.production.storage import MIULArtifactStore, queue_enabled

LOGGER = logging.getLogger(__name__)


def _aws_region() -> str | None:
    return os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or None


def _queue_url() -> str:
    return os.getenv("MIUL_EXTRACTION_QUEUE_URL", "").strip()


def _sqs_client():
    import boto3

    kwargs: dict[str, Any] = {}
    region = _aws_region()
    if region:
        kwargs["region_name"] = region
    return boto3.client("sqs", **kwargs)


def _receive_wait_seconds() -> int:
    return max(1, min(int(os.getenv("MIUL_WORKER_WAIT_SECONDS", "20")), 20))


def _visibility_timeout_seconds() -> int:
    return max(30, int(os.getenv("MIUL_WORKER_VISIBILITY_TIMEOUT_SECONDS", "1800")))


def _idle_sleep_seconds() -> float:
    return max(0.1, float(os.getenv("MIUL_WORKER_IDLE_SLEEP_SECONDS", "1.0")))


def _download_inputs(job: dict[str, Any], temp_dir: Path) -> tuple[list[Path], dict[str, Any]]:
    extraction_id = str(job["extraction_id"])
    store = MIULArtifactStore(extraction_id)

    pdf_paths: list[Path] = []
    for item in job.get("pdf_inputs") or []:
        if not isinstance(item, dict):
            continue
        filename = Path(str(item.get("filename") or "drawing.pdf")).name
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        destination = temp_dir / filename
        store.download_input_file(key, destination)
        pdf_paths.append(destination)

    dt_json: dict[str, Any] = {}
    dt_json_key = str(job.get("dt_json_key") or "").strip()
    if dt_json_key:
        loaded = store.read_input_json(dt_json_key)
        if isinstance(loaded, dict):
            dt_json = loaded

    return pdf_paths, dt_json


def _process_message(message: dict[str, Any]) -> None:
    body = json.loads(str(message.get("Body") or "{}"))
    extraction_id = str(body.get("extraction_id") or "").strip()
    if not extraction_id:
        raise RuntimeError("MIUL worker received a message without extraction_id")

    session = V4Session(extraction_id)
    session.set_status("extracting", "Worker started Sonnet Vision extraction...", progress=5)

    temp_dir = Path(tempfile.mkdtemp(prefix=f"miul-worker-{extraction_id[:8]}-"))
    try:
        pdf_paths, dt_json = _download_inputs(body, temp_dir)
        if not pdf_paths:
            raise RuntimeError(f"MIUL worker found no staged PDF inputs for extraction {extraction_id}")

        from mira.api.routers.miul import _run_extraction_background

        _run_extraction_background(extraction_id, pdf_paths, dt_json, temp_dir)
    except Exception as exc:
        LOGGER.exception("[MIUL-WORKER] Extraction %s failed", extraction_id)
        session.set_status("failed", str(exc), progress=0, error=str(exc))
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def run_forever() -> None:
    if not queue_enabled():
        raise RuntimeError("MIUL worker started without MIUL_EXTRACTION_QUEUE_URL configured")

    queue_url = _queue_url()
    client = _sqs_client()
    wait_seconds = _receive_wait_seconds()
    visibility_timeout = _visibility_timeout_seconds()

    LOGGER.info(
        "[MIUL-WORKER] Starting worker queue=%s wait_seconds=%s visibility_timeout=%s",
        queue_url,
        wait_seconds,
        visibility_timeout,
    )

    while True:
        response = client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=wait_seconds,
            VisibilityTimeout=visibility_timeout,
        )
        messages = response.get("Messages") or []
        if not messages:
            time.sleep(_idle_sleep_seconds())
            continue

        for message in messages:
            receipt_handle = str(message.get("ReceiptHandle") or "")
            try:
                _process_message(message)
            finally:
                if receipt_handle:
                    client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

